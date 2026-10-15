/**
 * Compile-time contract check (PLAN WP3 criterion 3.2): the JSON examples of
 * docs/ARCHITECTURE.md sections 3.11, 14 and 15, typed against `types.ts`.
 * Placeholders such as `{"...": "Metrics"}` in the document are expanded with
 * values consistent with the surrounding example. No `any`, no casts.
 * This module is never imported by the app; `tsc --noEmit` checks it.
 */
import type {
  ApproveResponse,
  Comparison,
  CpmResult,
  ErrorEnvelope,
  ExportFile,
  Health,
  InstantiateRequest,
  ListResponse,
  Metrics,
  PhaseCompletedEvent,
  PhaseStartedEvent,
  Problem,
  ProblemRecord,
  ProblemSummary,
  ProgressRunEvent,
  ReplanCreated,
  ReplanRequest,
  RunCancelledEvent,
  RunCompletedEvent,
  RunCreated,
  RunEvent,
  RunFailedEvent,
  RunQueuedEvent,
  RunStartedEvent,
  Schedule,
  ScheduleSummary,
  SolverRun,
  SolverRunRequest,
  TemplateInfo,
  ValidateResponse,
  CancelResponse,
} from "./types";

// 3.11
export const exampleProblem: Problem = {
  id: "p_7f3a",
  name: "Workshop week 43",
  description: "",
  domain: "manufacturing",
  horizon_start: "2026-10-19T00:00:00+05:30",
  horizon_days: 14,
  time_unit: "minutes",
  currency: "INR",
  terminology: {
    task: "Operation", tasks: "Operations", resource: "Machine",
    resources: "Machines", group: "Job", milestone: "Milestone",
    schedule: "Production schedule", deadline: "Due date",
  },
  tasks: [
    {
      id: "J1-1", name: "J1 Cutting", description: "", group: "J1", type: "activity",
      duration_minutes: 90, priority: 7, earliest_start: null,
      deadline: null, deadline_hard: false,
      requirements: [{ alternatives: ["CUT1"], units: 1 }], locked: null, metadata: {},
    },
    {
      id: "J1-2", name: "J1 Milling", description: "", group: "J1", type: "activity",
      duration_minutes: 120, priority: 7, earliest_start: null,
      deadline: "2026-10-21T18:00:00+05:30", deadline_hard: false,
      requirements: [{ alternatives: ["MILL1", "MILL2"], units: 1 }], locked: null, metadata: {},
    },
  ],
  resources: [
    {
      id: "CUT1", name: "Saw 1", kind: "machine", capacity: 1, cost_per_hour: 900.0,
      calendar: {
        weekly: {
          mon: [["06:00", "14:00"], ["14:00", "22:00"]],
          tue: [["06:00", "22:00"]], wed: [["06:00", "22:00"]],
          thu: [["06:00", "22:00"]], fri: [["06:00", "22:00"]],
          sat: [["06:00", "14:00"]],
        },
        blocked: [],
      },
      metadata: {},
    },
    {
      id: "MILL1", name: "Mill 1", kind: "machine", capacity: 1, cost_per_hour: 1200.0,
      calendar: {
        weekly: { mon: [["06:00", "22:00"]], tue: [["06:00", "22:00"]] },
        blocked: [{
          start: "2026-10-20T10:00:00+05:30",
          end: "2026-10-20T12:00:00+05:30", reason: "Maintenance",
        }],
      },
      metadata: {},
    },
    {
      id: "MILL2", name: "Mill 2", kind: "machine", capacity: 1, cost_per_hour: 1500.0,
      calendar: null, metadata: {},
    },
  ],
  dependencies: [{ predecessor: "J1-1", successor: "J1-2", type: "FS", lag_minutes: 0 }],
  objectives: { preset: "balanced", weights: { makespan: 1.0, tardiness: 1.0, cost: 0.2 } },
  metadata: {},
};

// 14.1
export const exampleHealth: Health = {
  status: "ok", version: "0.1.0", ortools_version: "9.15.6755", database: "ok",
};

// 14.2
export const exampleTemplates: ListResponse<TemplateInfo> = {
  items: [
    {
      id: "manufacturing", name: "Manufacturing", domain: "manufacturing",
      description: "Jobs with operations on machines, alternative machines, shifts and due dates.",
      terminology: {
        task: "Operation", tasks: "Operations", resource: "Machine", resources: "Machines",
        group: "Job", milestone: "Milestone", schedule: "Production schedule", deadline: "Due date",
      },
      parameters: [
        { name: "jobs", label: "Number of jobs", type: "int", default: 5, min: 1, max: 20, help: "" },
        { name: "due_in_days", label: "Latest due date (days)", type: "int", default: 5, min: 2, max: 30, help: "" },
      ],
    },
  ],
};

export const exampleInstantiate: InstantiateRequest = {
  name: "Workshop week 43", start_date: "2026-10-19", utc_offset: "+05:30", parameters: { jobs: 4 },
};

// 14.3
export const exampleProblemRecord: ProblemRecord = {
  id: "p_7f3a", version: 3, template_id: "manufacturing",
  created_at: "2026-10-15T09:00:00Z", updated_at: "2026-10-15T09:12:00Z",
  problem: exampleProblem,
};

export const exampleProblemSummary: ProblemSummary = {
  id: "p_7f3a", name: "Workshop week 43", domain: "manufacturing", version: 3,
  task_count: 12, resource_count: 5, updated_at: "2026-10-15T09:12:00Z",
  approved_schedule_id: "sch_91c2", latest_run: { id: "run_4d1e", status: "completed" },
};

export const exampleVersionMismatch: ErrorEnvelope = {
  error: { code: "VERSION_MISMATCH", message: "The plan was changed elsewhere.", details: { current_version: 5 } },
};

export const exampleExportFile: ExportFile = {
  format: "superplanner.problem", format_version: 1, exported_at: "2026-10-15T09:30:00Z",
  problem: exampleProblem,
};

// 14.4
export const exampleValidate: ValidateResponse = {
  problem_version: 3, ok: false,
  issues: [
    {
      code: "DEPENDENCY_CYCLE", severity: "error",
      message: "Operations \"J1 Cutting\" -> \"J1 Milling\" -> \"J1 Cutting\" form a loop; remove at least one of these dependencies.",
      task_ids: ["J1-1", "J1-2"], resource_ids: [], field: "dependencies",
    },
    {
      code: "UNUSED_RESOURCE", severity: "warning",
      message: "Machine \"Mill 2\" is not used by any operation.", task_ids: [], resource_ids: ["MILL2"], field: null,
    },
  ],
  cpm: null,
};

export const exampleCpm: CpmResult = {
  lower_bound_makespan_minutes: 570,
  tasks: { "J1-1": { es: 0, ef: 90, ls: 0, lf: 90, slack: 0, critical: true } },
  critical_path: ["J1-1", "J1-2"],
};

// 14.5
export const exampleRunRequest: SolverRunRequest = {
  strategy: "auto", time_limit_seconds: 10, seed: 0,
  objectives: { preset: "meet_deadlines", weights: { makespan: 1.0, tardiness: 1.0, cost: 0.2 } },
  max_alternatives: 2,
  ga: {
    population_size: null, max_generations: 300, stagnation_generations: 40,
    crossover_rate: 0.9, mutation_rate: 0.1, mutation_sigma: 0.1, swap_rate: 0.2,
    elite_count: 2, tournament_size: 3, archive_size: 10,
  },
  cpsat: { num_workers: 8, relative_gap: 0.0 },
};

export const exampleRunCreated: RunCreated = {
  run_id: "run_4d1e", status: "queued", problem_version_id: "pv_88aa",
  status_url: "/api/v1/solver-runs/run_4d1e", events_url: "/api/v1/solver-runs/run_4d1e/events",
};

export const exampleRunPreflightFailed: ErrorEnvelope = {
  error: { code: "PREFLIGHT_FAILED", message: "Fix 2 problems before optimizing.", details: { issues: exampleValidate.issues } },
};

const exampleMetrics: Metrics = {
  makespan_minutes: 1980, total_tardiness_minutes: 0, weighted_tardiness: 0, late_tasks: 0,
  hard_deadline_misses: 0, cost: 20100.0, scheduled_tasks: 12, total_tasks: 12,
  utilization: { CUT1: 0.31, MILL1: 0.42, MILL2: 0.12, ASM1: 0.38, OPS: 0.19 },
};

export const exampleSolverRun: SolverRun = {
  id: "run_4d1e", problem_id: "p_7f3a", problem_version_id: "pv_88aa", status: "completed",
  request: { strategy: "auto", time_limit_seconds: 10, seed: 0, "...": "..." },
  engine_version: "0.1.0",
  selection: {
    requested: "auto", used: ["heuristic", "cpsat"],
    reasons: ["Small/medium problem (12 tasks, 16 options): exact constraint solver seeded with the best heuristic."],
  },
  phases: [
    {
      solver: "heuristic", status: "completed", feasibility: "feasible", termination_reason: "completed",
      objectives: { makespan_minutes: 2280, weighted_tardiness: 0, cost: 21450.0, score: 1.2 },
      elapsed_seconds: 0.04,
    },
    {
      solver: "cpsat", status: "completed", feasibility: "feasible", termination_reason: "optimal",
      objectives: { makespan_minutes: 1980, weighted_tardiness: 0, cost: 20100.0, score: 1.06 },
      elapsed_seconds: 1.9,
    },
  ],
  feasibility: "feasible", termination_reason: "optimal", optimality_proven: true,
  objectives: { makespan_minutes: 1980, weighted_tardiness: 0, cost: 20100.0, score: 1.06 },
  metrics: exampleMetrics,
  diagnostics: [],
  error: null,
  primary_schedule_id: "sch_91c2", schedule_ids: ["sch_91c2", "sch_91c3"],
  source_schedule_id: null,
  created_at: "2026-10-15T09:20:00Z", started_at: "2026-10-15T09:20:00Z", finished_at: "2026-10-15T09:20:02Z",
  elapsed_seconds: 2.0,
};

export const exampleCancel: CancelResponse = { run_id: "run_4d1e", status: "cancelled", cancel_requested: true };

// 14.6
export const exampleScheduleSummary: ScheduleSummary = {
  id: "sch_91c2", problem_id: "p_7f3a", problem_version_id: "pv_88aa", solver_run_id: "run_4d1e",
  source_schedule_id: null, status: "candidate", rank: 0, label: "Recommended", solver: "cpsat",
  feasibility: "feasible",
  objectives: { makespan_minutes: 1980, weighted_tardiness: 0, cost: 20100.0, score: 1.06 },
  metrics: exampleMetrics, hard_violation_count: 0, soft_violation_count: 0,
  base_problem_version: 3, approved_problem_version: null,
  created_at: "2026-10-15T09:20:02Z", approved_at: null, superseded_at: null,
};

export const exampleSchedule: Schedule = {
  ...exampleScheduleSummary,
  horizon_start: "2026-10-19T00:00:00+05:30",
  placements: [
    {
      task_id: "J1-1", start: 360, end: 450, resource_ids: ["CUT1"],
      start_at: "2026-10-19T06:00:00+05:30", end_at: "2026-10-19T07:30:00+05:30",
    },
  ],
  violations: [
    {
      code: "DEADLINE_MISSED", severity: "soft", task_ids: ["J3-3"], resource_ids: [],
      message: "Operation \"J3 Assembly\" finishes 2h 15m after its due date (Wed 21 Oct 18:00).",
      details: { deadline: 3960, end: 4095, minutes_late: 135 },
    },
  ],
  explanation: {
    tasks: {
      "J1-1": {
        task_id: "J1-1",
        reasons: [{
          code: "CALENDAR", message: "Waits for Saw 1 to open at Mon 19 Oct 06:00.",
          related_task_ids: [], resource_ids: ["CUT1"],
        }],
        on_critical_chain: true, cpm_critical: true, cpm_slack_minutes: 0,
        lateness_minutes: 0, deadline_status: "none",
      },
    },
    critical_chain: ["J1-1", "J1-2"], cpm_critical_path: ["J1-1", "J1-2"],
    summary: ["All 12 Operations finish on time.", "Completion is driven by the chain J1 Cutting -> J1 Milling."],
  },
};

export const exampleApprove: ApproveResponse = {
  schedule: { ...exampleScheduleSummary, status: "approved", approved_at: "2026-10-15T09:25:00Z", approved_problem_version: 3 },
  superseded_schedule_id: null,
};

export const exampleComparison: Comparison = {
  a: exampleScheduleSummary,
  b: { ...exampleScheduleSummary, id: "sch_91c3", rank: 1, label: "Cheapest" },
  metric_deltas: {
    makespan_minutes: -300, total_tardiness_minutes: 0, weighted_tardiness: 0,
    late_tasks: 0, cost: -1350.0,
  },
  task_deltas: [
    {
      task_id: "J1-2", name: "J1 Milling", in_a: true, in_b: true,
      start_a: 450, start_b: 450, end_a: 570, end_b: 570, start_delta_minutes: 0,
      end_delta_minutes: 0, resources_a: ["MILL1"], resources_b: ["MILL2"], resource_changed: true,
    },
  ],
  changed_task_count: 5,
};

export const exampleReplan: ReplanRequest = {
  cutoff: "2026-10-20T12:00:00+05:30",
  changes: {
    task_updates: [{ id: "J2-2", duration_minutes: 180 }],
    add_tasks: [],
    remove_task_ids: [],
    resource_unavailable: [{
      resource_id: "MILL1", start: "2026-10-20T12:00:00+05:30",
      end: "2026-10-21T06:00:00+05:30", reason: "Breakdown",
    }],
  },
  run: { strategy: "auto", time_limit_seconds: 10 },
  expected_problem_version: 3,
};

export const exampleReplanCreated: ReplanCreated = {
  ...exampleRunCreated, source_schedule_id: "sch_91c2", problem_version: 4,
};

// 15 - one event of each type
const base = { run_id: "run_4d1e", ts: "2026-10-15T09:20:01.200Z" };

export const evQueued: RunQueuedEvent = { ...base, seq: 1, type: "run_queued", elapsed_seconds: 0, problem_version_id: "pv_88aa" };
export const evStarted: RunStartedEvent = { ...base, seq: 2, type: "run_started", elapsed_seconds: 0.01, strategy_requested: "auto" };
export const evPhaseStarted: PhaseStartedEvent = {
  ...base, seq: 3, type: "phase_started", elapsed_seconds: 0.02, solver: "heuristic",
  reason: "Baseline: fast priority rules give a first schedule and reference values.",
};
export const evProgress: ProgressRunEvent = {
  run_id: "run_4d1e", seq: 7, type: "progress", ts: "2026-10-15T09:20:01.200Z", elapsed_seconds: 1.2,
  solver: "cpsat", iteration: 4, best_score: 1.08,
  best_objectives: { makespan_minutes: 2010, weighted_tardiness: 0, cost: 20100.0, score: 1.08 },
  feasible_found: true, extra: { best_bound: 0.97 },
};
export const evPhaseCompleted: PhaseCompletedEvent = {
  ...base, seq: 8, type: "phase_completed", elapsed_seconds: 1.9, solver: "cpsat",
  status: "completed", feasibility: "feasible", termination_reason: "optimal",
  objectives: { makespan_minutes: 1980, weighted_tardiness: 0, cost: 20100.0, score: 1.06 },
};
export const evCompleted: RunCompletedEvent = {
  ...base, seq: 9, type: "run_completed", elapsed_seconds: 2.0, feasibility: "feasible",
  termination_reason: "optimal", optimality_proven: true,
  objectives: { makespan_minutes: 1980, weighted_tardiness: 0, cost: 20100.0, score: 1.06 },
  primary_schedule_id: "sch_91c2", schedule_ids: ["sch_91c2", "sch_91c3"],
};
export const evCancelled: RunCancelledEvent = {
  ...base, seq: 9, type: "run_cancelled", elapsed_seconds: 1.0, primary_schedule_id: null, schedule_ids: [],
};
export const evFailed: RunFailedEvent = {
  ...base, seq: 4, type: "run_failed", elapsed_seconds: 0.3, error: "Server restarted before the run finished.",
};

export const allEvents: RunEvent[] = [
  evQueued, evStarted, evPhaseStarted, evProgress, evPhaseCompleted, evCompleted, evCancelled, evFailed,
];
