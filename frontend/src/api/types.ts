/**
 * TypeScript mirrors of the SuperPlanner API contract (docs/ARCHITECTURE.md
 * sections 3, 7, 9, 11, 12, 14, 15). JSON field names are snake_case exactly as
 * the server sends them. Keep this file in sync with the document; the file
 * `contractExamples.ts` type-checks the document's JSON examples against it.
 */

// ---------------------------------------------------------------- 3.1 common
export type Id = string;
/** ISO-8601 datetime with UTC offset, e.g. "2026-10-19T08:00:00+05:30". */
export type AwareDatetime = string;
/** "HH:MM" or "24:00" (end only). */
export type HHMM = string;
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

// ---------------------------------------------------------------- 3.3
export interface Terminology {
  task: string;
  tasks: string;
  resource: string;
  resources: string;
  group: string;
  milestone: string;
  schedule: string;
  deadline: string;
}

// ---------------------------------------------------------------- 3.5 - 3.10
export interface Requirement {
  alternatives: Id[];
  units: number;
}

export interface Lock {
  start: AwareDatetime;
  resource_ids: Id[] | null;
}

export type TaskType = "activity" | "milestone";

/** Three-point duration estimate (PHASE2.md 2.14); `duration_minutes` is its PERT expected value. */
export interface DurationEstimate {
  optimistic_minutes: number;
  likely_minutes: number;
  pessimistic_minutes: number;
}

export interface Task {
  id: Id;
  name: string;
  description: string;
  group: string | null;
  type: TaskType;
  duration_minutes: number;
  priority: number;
  earliest_start: AwareDatetime | null;
  deadline: AwareDatetime | null;
  deadline_hard: boolean;
  requirements: Requirement[];
  locked: Lock | null;
  metadata: Record<string, unknown>;
  /** optional; absent on documents without a range. Activities only. */
  duration_estimate?: DurationEstimate | null;
}

export type DependencyType = "FS" | "SS" | "FF" | "SF";

export interface Dependency {
  predecessor: Id;
  successor: Id;
  type: DependencyType;
  lag_minutes: number;
}

export type TimeWindow = [HHMM, HHMM];

export interface BlockedInterval {
  start: AwareDatetime;
  end: AwareDatetime;
  reason: string;
}

export interface Calendar {
  weekly: Partial<Record<Weekday, TimeWindow[]>> | null;
  blocked: BlockedInterval[];
}

export interface Resource {
  id: Id;
  name: string;
  kind: string;
  capacity: number;
  cost_per_hour: number;
  calendar: Calendar | null;
  metadata: Record<string, unknown>;
}

export type Preset = "balanced" | "finish_asap" | "meet_deadlines" | "lowest_cost" | "custom";

export interface Weights {
  makespan: number;
  tardiness: number;
  cost: number;
}

export interface Objectives {
  preset: Preset;
  weights: Weights;
}

// ---------------------------------------------------------------- 3.2
export interface Problem {
  id: Id;
  name: string;
  description: string;
  domain: string;
  horizon_start: AwareDatetime;
  horizon_days: number;
  time_unit: "minutes";
  currency: string;
  terminology: Terminology;
  tasks: Task[];
  resources: Resource[];
  dependencies: Dependency[];
  objectives: Objectives;
  metadata: Record<string, unknown>;
}

// ---------------------------------------------------------------- 7.1, 7.4, 7.5
export interface Placement {
  task_id: Id;
  start: number;
  end: number;
  resource_ids: Id[];
}

export interface ObjectiveValues {
  makespan_minutes: number;
  weighted_tardiness: number;
  cost: number;
  score: number;
}

export type Feasibility = "feasible" | "infeasible" | "unknown";

export type TerminationReason =
  | "optimal"
  | "proven_infeasible"
  | "time_limit"
  | "generation_limit"
  | "stagnation"
  | "completed"
  | "cancelled"
  | "preflight_failed"
  | "no_solution"
  | "error";

export type PhaseName = "heuristic" | "cpsat" | "ga" | "cpm";

export type ViolationCode =
  | "TASK_MISSING"
  | "TASK_DUPLICATE"
  | "UNKNOWN_TASK"
  | "DURATION_MISMATCH"
  | "OUTSIDE_HORIZON"
  | "EARLIEST_START_VIOLATED"
  | "DEPENDENCY_VIOLATED"
  | "RESOURCE_COUNT_MISMATCH"
  | "RESOURCE_NOT_ELIGIBLE"
  | "RESOURCE_DUPLICATE"
  | "CAPACITY_EXCEEDED"
  | "CALENDAR_VIOLATED"
  | "LOCK_VIOLATED"
  | "HARD_DEADLINE_MISSED"
  | "DEADLINE_MISSED";

export interface Violation {
  /** One of ViolationCode; typed as string for forward compatibility. */
  code: string;
  severity: "hard" | "soft";
  task_ids: Id[];
  resource_ids: Id[];
  message: string;
  details: Record<string, unknown>;
}

export interface Metrics {
  makespan_minutes: number;
  total_tardiness_minutes: number;
  weighted_tardiness: number;
  late_tasks: number;
  hard_deadline_misses: number;
  cost: number;
  scheduled_tasks: number;
  total_tasks: number;
  utilization: Record<Id, number>;
}

// ---------------------------------------------------------------- 7.6
export type Strategy = "auto" | "heuristic" | "cpsat" | "ga" | "hybrid";

export interface Selection {
  requested: string;
  used: string[];
  reasons: string[];
}

export interface PhaseSummary {
  solver: string;
  status: "completed" | "cancelled" | "failed";
  feasibility: Feasibility;
  termination_reason: TerminationReason;
  objectives: ObjectiveValues | null;
  elapsed_seconds: number;
}

// ---------------------------------------------------------------- 8.5 / 7.3
export interface GaParams {
  population_size: number | null;
  max_generations: number;
  stagnation_generations: number;
  crossover_rate: number;
  mutation_rate: number;
  mutation_sigma: number;
  swap_rate: number;
  elite_count: number;
  tournament_size: number;
  archive_size: number;
}

export interface CpSatParams {
  num_workers: number;
  relative_gap: number;
}

// ---------------------------------------------------------------- 9.1 / 9.2
export type IssueCode =
  | "NO_TASKS"
  | "TOO_LARGE"
  | "DUPLICATE_ID"
  | "UNKNOWN_RESOURCE"
  | "UNKNOWN_TASK"
  | "SELF_DEPENDENCY"
  | "DUPLICATE_DEPENDENCY"
  | "DEPENDENCY_CYCLE"
  | "UNITS_EXCEED_CAPACITY"
  | "NO_FITTING_WINDOW"
  | "INVALID_CALENDAR"
  | "EMPTY_CALENDAR"
  | "EARLIEST_AFTER_HORIZON"
  | "DEADLINE_BEFORE_EARLIEST"
  | "DEADLINE_BEFORE_HORIZON"
  | "LOCK_INVALID"
  | "HARD_DEADLINE_IMPOSSIBLE"
  | "HORIZON_TOO_SHORT"
  | "SOFT_DEADLINE_UNREACHABLE"
  | "UNUSED_RESOURCE"
  | "MILESTONE_WITH_LOCKED_RESOURCES"
  | "LAG_OUT_OF_RANGE";

export interface Issue {
  /** One of IssueCode; typed as string for forward compatibility. */
  code: string;
  severity: "error" | "warning";
  message: string;
  task_ids: Id[];
  resource_ids: Id[];
  field: string | null;
}

export interface PreflightReport {
  ok: boolean;
  issues: Issue[];
}

export interface CpmTask {
  es: number;
  ef: number;
  ls: number;
  lf: number;
  slack: number;
  critical: boolean;
}

export interface CpmResult {
  lower_bound_makespan_minutes: number;
  tasks: Record<Id, CpmTask>;
  critical_path: Id[];
}

/** Engine ValidateReport (9.2). */
export interface ValidateReport {
  ok: boolean;
  issues: Issue[];
  cpm: CpmResult | null;
}

/** API response of POST /problems/{id}/validate (14.4). */
export interface ValidateResponse extends ValidateReport {
  problem_version: number;
}

// ---------------------------------------------------------------- 11
export type StartReasonCode =
  | "LOCKED"
  | "HORIZON_START"
  | "EARLIEST_START"
  | "DEPENDENCY"
  | "RESOURCE_BUSY"
  | "CALENDAR"
  | "OPTIMIZER_CHOICE"
  | "NOT_SCHEDULED";

export interface StartReason {
  code: StartReasonCode;
  message: string;
  related_task_ids: Id[];
  resource_ids: Id[];
}

export type DeadlineStatus = "none" | "on_time" | "late_soft" | "late_hard";

export interface TaskExplanation {
  task_id: Id;
  reasons: StartReason[];
  on_critical_chain: boolean;
  cpm_critical: boolean;
  cpm_slack_minutes: number;
  lateness_minutes: number;
  deadline_status: DeadlineStatus;
}

/** PERT note for plans with duration ranges (PHASE2.md 2.14). */
export interface DurationRisk {
  tasks_with_range: number;
  chain_task_ids: Id[];
  chain_expected_minutes: number;
  chain_optimistic_minutes: number;
  chain_pessimistic_minutes: number;
  chain_sigma_minutes: number;
  buffer_85_minutes: number;
  message: string;
}

export interface ScheduleExplanation {
  tasks: Record<Id, TaskExplanation>;
  critical_chain: Id[];
  cpm_critical_path: Id[];
  summary: string[];
  /** null/absent when no task has a duration range */
  duration_risk?: DurationRisk | null;
}

// ---------------------------------------------------------------- 12 / 14.2
export type TemplateParameterType = "int" | "date" | "string" | "string_list";

export interface TemplateParameter {
  name: string;
  label: string;
  type: TemplateParameterType;
  default: unknown;
  min: number | null;
  max: number | null;
  help: string;
}

export interface TemplateInfo {
  id: string;
  name: string;
  domain: string;
  description: string;
  terminology: Terminology;
  parameters: TemplateParameter[];
}

export interface InstantiateRequest {
  name?: string;
  start_date?: string;
  utc_offset?: string;
  parameters?: Record<string, unknown>;
}

// ---------------------------------------------------------------- 14.3
export interface ProblemRecord {
  id: Id;
  version: number;
  template_id: string | null;
  created_at: string;
  updated_at: string;
  problem: Problem;
}

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface ProblemSummary {
  id: Id;
  name: string;
  domain: string;
  version: number;
  task_count: number;
  resource_count: number;
  updated_at: string;
  approved_schedule_id: Id | null;
  latest_run: { id: Id; status: RunStatus } | null;
}

export interface ExportFile {
  format: "superplanner.problem";
  format_version: number;
  exported_at: string;
  problem: Problem;
}

export interface ListResponse<T> {
  items: T[];
}

// ---------------------------------------------------------------- 14.5
export interface SolverRunRequest {
  strategy?: Strategy;
  time_limit_seconds?: number;
  seed?: number;
  objectives?: Objectives | null;
  max_alternatives?: number;
  ga?: Partial<GaParams>;
  cpsat?: Partial<CpSatParams>;
}

export interface RunCreated {
  run_id: Id;
  status: RunStatus;
  problem_version_id: Id;
  status_url: string;
  events_url: string;
}

export interface SolverRun {
  id: Id;
  problem_id: Id;
  problem_version_id: Id;
  status: RunStatus;
  request: SolverRunRequest & Record<string, unknown>;
  engine_version: string;
  selection: Selection | null;
  phases: PhaseSummary[] | null;
  feasibility: Feasibility | null;
  termination_reason: TerminationReason | null;
  optimality_proven: boolean | null;
  objectives: ObjectiveValues | null;
  metrics: Metrics | null;
  diagnostics: string[];
  error: string | null;
  primary_schedule_id: Id | null;
  schedule_ids: Id[];
  source_schedule_id: Id | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
}

export interface CancelResponse {
  run_id: Id;
  status: RunStatus;
  cancel_requested: boolean;
}

// ---------------------------------------------------------------- 14.6
export type ScheduleStatus = "candidate" | "approved" | "superseded";

export interface ScheduleSummary {
  id: Id;
  problem_id: Id;
  problem_version_id: Id;
  solver_run_id: Id | null;
  source_schedule_id: Id | null;
  status: ScheduleStatus;
  rank: number;
  label: string;
  solver: string;
  feasibility: Feasibility;
  objectives: ObjectiveValues | null;
  metrics: Metrics | null;
  hard_violation_count: number;
  soft_violation_count: number;
  base_problem_version: number;
  approved_problem_version: number | null;
  created_at: string;
  approved_at: string | null;
  superseded_at: string | null;
}

export interface PlacementOut extends Placement {
  start_at: AwareDatetime;
  end_at: AwareDatetime;
}

export interface Schedule extends ScheduleSummary {
  horizon_start: AwareDatetime;
  placements: PlacementOut[];
  violations: Violation[];
  explanation: ScheduleExplanation | null;
}

export interface ApproveRequest {
  note?: string;
}

export interface ApproveResponse {
  schedule: ScheduleSummary;
  superseded_schedule_id: Id | null;
}

export interface MetricDeltas {
  makespan_minutes: number;
  total_tardiness_minutes: number;
  weighted_tardiness: number;
  late_tasks: number;
  cost: number;
}

export interface TaskDelta {
  task_id: Id;
  name: string;
  in_a: boolean;
  in_b: boolean;
  start_a: number | null;
  start_b: number | null;
  end_a: number | null;
  end_b: number | null;
  start_delta_minutes: number | null;
  end_delta_minutes: number | null;
  resources_a: Id[];
  resources_b: Id[];
  resource_changed: boolean;
}

export interface Comparison {
  a: ScheduleSummary;
  b: ScheduleSummary;
  metric_deltas: MetricDeltas;
  task_deltas: TaskDelta[];
  changed_task_count: number;
}

export type TaskUpdate = { id: Id } & Partial<
  Pick<
    Task,
    | "name"
    | "duration_minutes"
    | "priority"
    | "earliest_start"
    | "deadline"
    | "deadline_hard"
    | "requirements"
  >
>;

export interface ResourceUnavailable {
  resource_id: Id;
  start: AwareDatetime;
  end: AwareDatetime;
  reason: string;
}

export interface ReplanChanges {
  task_updates?: TaskUpdate[];
  add_tasks?: Task[];
  remove_task_ids?: Id[];
  resource_unavailable?: ResourceUnavailable[];
}

export interface ReplanRequest {
  cutoff: AwareDatetime;
  changes?: ReplanChanges;
  run?: SolverRunRequest;
  expected_problem_version?: number;
}

export interface ReplanCreated extends RunCreated {
  source_schedule_id: Id;
  problem_version: number;
}

// ---------------------------------------------------------------- 14.1
export interface Health {
  status: "ok" | "degraded";
  version: string;
  ortools_version: string;
  database: "ok" | "error";
}

// ---------------------------------------------------------------- 14 errors
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

// ---------------------------------------------------------------- 15 SSE
interface RunEventBase {
  run_id: Id;
  seq: number;
  ts: string;
  elapsed_seconds: number;
}

export interface RunQueuedEvent extends RunEventBase {
  type: "run_queued";
  problem_version_id: Id;
}

export interface RunStartedEvent extends RunEventBase {
  type: "run_started";
  strategy_requested: string;
}

export interface PhaseStartedEvent extends RunEventBase {
  type: "phase_started";
  solver: string;
  reason: string;
}

export interface ProgressRunEvent extends RunEventBase {
  type: "progress";
  solver: string;
  iteration: number | null;
  best_score: number | null;
  best_objectives: ObjectiveValues | null;
  feasible_found: boolean;
  extra: Record<string, unknown>;
}

export interface PhaseCompletedEvent extends RunEventBase {
  type: "phase_completed";
  solver: string;
  status: "completed" | "cancelled" | "failed";
  feasibility: Feasibility;
  termination_reason: TerminationReason;
  objectives: ObjectiveValues | null;
}

export interface RunCompletedEvent extends RunEventBase {
  type: "run_completed";
  feasibility: Feasibility;
  termination_reason: TerminationReason;
  optimality_proven: boolean;
  objectives: ObjectiveValues | null;
  primary_schedule_id: Id | null;
  schedule_ids: Id[];
}

export interface RunCancelledEvent extends RunEventBase {
  type: "run_cancelled";
  primary_schedule_id: Id | null;
  schedule_ids: Id[];
}

export interface RunFailedEvent extends RunEventBase {
  type: "run_failed";
  error: string;
}

/** PHASE2B 2.6: the worker running this run was lost or stopped; the run starts again from scratch. */
export type RequeueReason = "lease_expired" | "transient_error" | "worker_shutdown";

export interface RunRequeuedEvent extends RunEventBase {
  type: "run_requeued";
  attempt: number;
  max_attempts: number;
  reason: RequeueReason | string;
  retry_at: string;
}

export type RunEvent =
  | RunQueuedEvent
  | RunStartedEvent
  | PhaseStartedEvent
  | ProgressRunEvent
  | PhaseCompletedEvent
  | RunCompletedEvent
  | RunCancelledEvent
  | RunFailedEvent
  | RunRequeuedEvent;

export type RunEventType = RunEvent["type"];

export const RUN_EVENT_TYPES: RunEventType[] = [
  "run_queued",
  "run_started",
  "phase_started",
  "progress",
  "phase_completed",
  "run_completed",
  "run_cancelled",
  "run_failed",
  "run_requeued",
];

export const TERMINAL_EVENT_TYPES: RunEventType[] = ["run_completed", "run_cancelled", "run_failed"];

export const ACTIVE_RUN_STATUSES: RunStatus[] = ["queued", "running"];

// ---------------------------------------------------------------- 3.10 presets
export const PRESET_WEIGHTS: Record<Exclude<Preset, "custom">, Weights> = {
  balanced: { makespan: 1.0, tardiness: 1.0, cost: 0.2 },
  finish_asap: { makespan: 1.0, tardiness: 0.3, cost: 0.0 },
  meet_deadlines: { makespan: 0.2, tardiness: 1.0, cost: 0.0 },
  lowest_cost: { makespan: 0.2, tardiness: 0.5, cost: 1.0 },
};

export const DEFAULT_GA_PARAMS: GaParams = {
  population_size: null,
  max_generations: 300,
  stagnation_generations: 40,
  crossover_rate: 0.9,
  mutation_rate: 0.1,
  mutation_sigma: 0.1,
  swap_rate: 0.2,
  elite_count: 2,
  tournament_size: 3,
  archive_size: 10,
};

export const DEFAULT_CPSAT_PARAMS: CpSatParams = { num_workers: 8, relative_gap: 0.0 };

export const DEFAULT_TERMINOLOGY: Terminology = {
  task: "Task",
  tasks: "Tasks",
  resource: "Resource",
  resources: "Resources",
  group: "Group",
  milestone: "Milestone",
  schedule: "Schedule",
  deadline: "Deadline",
};
