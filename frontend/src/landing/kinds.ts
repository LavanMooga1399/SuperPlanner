/**
 * The four kinds of plan offered on the landing page (PHASE2.md 3.1, 3.2).
 * Scheduling kinds map to an existing plan type (`Problem.domain`, P2D 8 item 6) and template;
 * "money" leads to the finance module.
 */
import type { Calendar, Terminology } from "../api/types";
import type { IconName } from "../components/Icon";
import { t } from "../lib/i18n";

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
    label: t("studio.kinds.str.projectOrSchedule"),
    description: t("studio.kinds.str.tasksPeopleAndDeadlines"),
    icon: "briefcase",
    scheduling: true,
    templateId: "project",
    terminology: {
      task: t("studio.kinds.str.task"), tasks: t("studio.kinds.str.tasks"), resource: t("studio.kinds.str.teamMember"), resources: t("studio.kinds.str.team"), group: t("studio.kinds.str.workstream"),
      milestone: t("studio.kinds.str.milestone"), schedule: t("studio.kinds.str.projectSchedule"), deadline: t("studio.kinds.str.deadline"),
    },
    starterResource: { id: "ME", name: t("studio.kinds.str.me"), kind: "person", calendar: { weekly: weekdays([["09:00", "17:00"]]), blocked: [] } },
    planNoun: "project",
  },
  study: {
    kind: "study",
    label: t("studio.kinds.str.studyPlan"),
    description: t("studio.kinds.str.subjectsRevisionAndAnExam"),
    icon: "book",
    scheduling: true,
    templateId: "exam_prep",
    terminology: {
      task: t("studio.kinds.str.studySession"), tasks: t("studio.kinds.str.studySessions"), resource: t("studio.kinds.str.studyTime"), resources: t("studio.kinds.str.studyTime"), group: t("studio.kinds.str.subject"),
      milestone: t("studio.kinds.str.exam"), schedule: t("studio.kinds.str.studyPlan"), deadline: t("studio.kinds.str.targetDate"),
    },
    starterResource: {
      id: "STUDENT",
      name: t("studio.kinds.str.myStudyTime"),
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
    label: t("studio.kinds.str.production"),
    description: t("studio.kinds.str.ordersMachinesAndShifts"),
    icon: "factory",
    scheduling: true,
    templateId: "manufacturing",
    terminology: {
      task: t("studio.kinds.str.operation"), tasks: t("studio.kinds.str.operations"), resource: t("studio.kinds.str.machine"), resources: t("studio.kinds.str.machines"), group: t("studio.kinds.str.job"),
      milestone: t("studio.kinds.str.milestone"), schedule: t("studio.kinds.str.productionSchedule"), deadline: t("studio.kinds.str.dueDate"),
    },
    starterResource: {
      id: "M1",
      name: t("studio.kinds.str.machine1"),
      kind: "machine",
      calendar: { weekly: { ...weekdays([["06:00", "14:00"], ["14:00", "22:00"]]), sat: [["06:00", "14:00"]] }, blocked: [] },
    },
    planNoun: "production",
  },
  money: {
    kind: "money",
    label: t("studio.kinds.str.moneyGoals"),
    description: t("studio.kinds.str.incomeSavingsAndGoalsLike"),
    icon: "star",
    scheduling: false,
    templateId: null,
    terminology: null,
    starterResource: null,
    planNoun: "money",
  },
};

export const ACTION_LABEL: Record<StartAction, string> = {
  describe: t("studio.kinds.str.describeIt"),
  example: t("studio.kinds.str.startFromAnExample"),
  import: t("studio.kinds.str.importATable"),
  steps: t("studio.kinds.str.buildStepByStep"),
};

export const ACTION_HINT: Record<StartAction, string> = {
  describe: t("studio.kinds.str.writeItInYourOwn"),
  example: t("studio.kinds.str.beginWithAReadyMade"),
  import: t("studio.kinds.str.pasteFromASpreadsheetOr"),
  steps: t("studio.kinds.str.fillInTheDetailsYourself"),
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
