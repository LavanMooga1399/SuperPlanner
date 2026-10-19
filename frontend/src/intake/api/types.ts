/**
 * TypeScript mirrors of the intake models (PHASE2.md 2.3-2.5, 2.9, 2.13, 2.15), hand-written like
 * `src/api/types.ts`. Request bodies use exactly these field names (the server forbids extra fields).
 */
import type { Problem, ValidateReport } from "../../api/types";
import type { CashflowSummary, FinancePlan, FinancePreflightReport } from "../../finance/api/types";

export type Domain = "schedule" | "finance";
export type ScheduleKind = "project" | "study" | "production" | "generic";
export type DurationUnit = "minutes" | "hours" | "days" | "weeks";
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export type Frequency = "monthly" | "quarterly" | "half_yearly" | "yearly" | "once";
export type Priority = "must" | "should" | "nice";
/** "YYYY-MM-DD" */
export type DateStr = string;
/** "YYYY-MM" */
export type Month = string;

// ---------------------------------------------------------------- 2.3 common
export interface ExtractContext {
  today: DateStr;
  utc_offset: string;
  locale: string;
  currency: string;
  kind?: ScheduleKind | null;
}

export interface SourceSpan {
  /** Unicode code points into the submitted text */
  start: number;
  end: number;
  text: string;
}

export interface CellRef {
  row: number;
  column: number;
}

export type ProvenanceSource = "text" | "table" | "ai" | "default" | "answer" | "edit" | "derived";

export interface Provenance {
  source: ProvenanceSource;
  confidence: number;
  span?: SourceSpan | null;
  cell?: CellRef | null;
  note?: string;
}

export interface QuestionOption {
  value: string;
  label: string;
}

export type QuestionKind =
  | "number"
  | "money"
  | "percent"
  | "duration"
  | "date"
  | "month"
  | "choice"
  | "multi_choice"
  | "text"
  | "confirm"
  | "people"
  | "working_time";

export interface Question {
  id: string;
  code: string;
  path: string | null;
  kind: QuestionKind;
  prompt: string;
  help: string;
  options: QuestionOption[];
  default: unknown;
  default_label: string;
  required: boolean;
  reason: "missing" | "ambiguous" | "low_confidence" | "conflict" | "confirm_default";
  span: SourceSpan | null;
  error: string | null;
}

export interface Answer {
  question_id: string;
  value?: unknown;
  use_default?: boolean;
  skip?: boolean;
}

export interface IntakeNote {
  code: string;
  severity: "info" | "warning";
  message: string;
  span?: SourceSpan | null;
}

export interface ExtractorInfo {
  requested: "rule" | "ai";
  used: "rule" | "ai+rule";
  ai_available: boolean;
  fallback_code: string | null;
  fallback_message: string | null;
  model: string | null;
}

// ---------------------------------------------------------------- 2.4 schedule draft
export interface DraftDuration {
  optimistic: number;
  likely: number;
  pessimistic: number;
  unit: DurationUnit;
}

export interface WindowHM {
  start: string;
  end: string;
}

export interface WorkingTime {
  days: Weekday[];
  windows: WindowHM[];
  weekend_windows?: WindowHM[] | null;
}

export type DraftResourceKind = "person" | "machine" | "room" | "equipment" | "generic";

export interface DraftResource {
  key: string;
  name: string;
  kind: DraftResourceKind;
  count: number;
}

export interface DraftTask {
  key: string;
  name: string;
  milestone: boolean;
  duration: DraftDuration | null;
  after: string[];
  resources: string[];
  resource_mode: "any" | "all";
  deadline: DateStr | null;
  deadline_hard: boolean;
  earliest_start: DateStr | null;
  priority: number | null;
  group: string | null;
  notes: string;
}

export type ScheduleObjective = "balanced" | "finish_asap" | "meet_deadlines" | "lowest_cost";

export interface ScheduleDraft {
  domain: "schedule";
  kind: ScheduleKind;
  name: string;
  start_date: DateStr | null;
  horizon_days: number | null;
  working_time: WorkingTime | null;
  objective: ScheduleObjective | null;
  tasks: DraftTask[];
  resources: DraftResource[];
  provenance: Record<string, Provenance>;
  dismissed: string[];
}

// ---------------------------------------------------------------- 2.5 finance draft
export interface DraftAmount {
  low: number;
  high: number;
}

export interface DraftProfile {
  age: number | null;
  retirement_age: number | null;
  risk_tolerance: number | null;
  currency: string;
  locale: string;
}

export type IncomeKind = "salary" | "business" | "rental" | "pension" | "interest" | "other";
export type DebtKind = "home" | "vehicle" | "education" | "personal" | "credit_card" | "other";
export type GoalKind = "retirement" | "education" | "home" | "vehicle" | "travel" | "wedding" | "business" | "other";

export interface DraftIncome {
  key: string;
  name: string;
  kind: IncomeKind;
  amount: DraftAmount | null;
  frequency: Frequency;
  growth_pct: number | null;
  inflation_linked: boolean;
  interruptible: boolean;
  end_month: Month | null;
}

export interface DraftExpense {
  key: string;
  name: string;
  category: string;
  amount: DraftAmount | null;
  frequency: Frequency;
  essential: boolean | null;
  inflation_pct: number | null;
  end_month: Month | null;
}

export interface DraftDebt {
  key: string;
  name: string;
  kind: DebtKind;
  balance: DraftAmount | null;
  interest_rate_pct: number | null;
  emi: DraftAmount | null;
  remaining_months: number | null;
}

export interface DraftHolding {
  key: string;
  name: string;
  asset_class_id: string | null;
  amount: DraftAmount | null;
  locked_until_month: Month | null;
}

export interface DraftGoal {
  key: string;
  name: string;
  kind: GoalKind;
  target: DraftAmount | null;
  target_month: Month | null;
  priority: Priority | null;
  flexibility_months: number;
  inflation_pct: number | null;
}

export interface FinanceDraft {
  domain: "finance";
  name: string;
  start_month: Month | null;
  profile: DraftProfile;
  incomes: DraftIncome[];
  expenses: DraftExpense[];
  debts: DraftDebt[];
  holdings: DraftHolding[];
  goals: DraftGoal[];
  emergency_fund_months: number | null;
  provenance: Record<string, Provenance>;
  dismissed: string[];
}

export type AnyDraft = ScheduleDraft | FinanceDraft;

// ---------------------------------------------------------------- 2.15 requests / responses
export interface DescribeRequest {
  text: string;
  context: ExtractContext;
  use_ai: boolean;
}

export interface IntakeResponse<D extends AnyDraft> {
  draft: D;
  questions: Question[];
  notes: IntakeNote[];
  row_notes: IntakeNote[];
  extractor: ExtractorInfo;
  ready: boolean;
}

export type ScheduleIntakeResponse = IntakeResponse<ScheduleDraft>;
export type FinanceIntakeResponse = IntakeResponse<FinanceDraft>;

export interface DurationSummary {
  tasks_with_range: number;
  expected_work_minutes: number;
  optimistic_work_minutes: number;
  pessimistic_work_minutes: number;
}

export interface ScheduleBuildResult {
  ready: boolean;
  problem: Problem | null;
  report: ValidateReport | null;
  blocking: Question[];
  parts: Record<string, string[]>;
  duration_summary: DurationSummary | null;
}

export interface FinanceBuildResult {
  ready: boolean;
  plan: FinancePlan | null;
  preflight: FinancePreflightReport | null;
  cashflow: CashflowSummary | null;
  blocking: Question[];
}

export type BuildResult = ScheduleBuildResult | FinanceBuildResult;

export interface Capabilities {
  ai_available: boolean;
  ai_reason: string | null;
  provider: string;
  model: string;
  privacy_notice: string;
  limits: { max_text_chars: number; max_table_chars: number; max_table_rows: number; max_table_columns: number };
  schedule_kinds: ScheduleKind[];
}

// ---------------------------------------------------------------- 2.13 tables
export type Delimiter = "\t" | "," | ";" | "|";

export interface TableColumn {
  index: number;
  header: string | null;
  samples: string[];
  suggested_field: string | null;
  confidence: number;
}

export interface TableParseResult {
  delimiter: Delimiter;
  has_header: boolean;
  row_count: number;
  columns: TableColumn[];
  preview: string[][];
  warnings: string[];
}

export interface ColumnMapping {
  column: number;
  field: string | null;
}

export interface TableOptions {
  duration_unit: DurationUnit;
  default_row_kind: "income" | "expense" | "goal" | "debt" | "holding";
  amount_frequency: Frequency;
  predecessor_ref: "auto" | "id" | "name" | "row";
}

export interface TableParseRequest {
  text: string;
  delimiter: "auto" | Delimiter;
  has_header: boolean | null;
}

export interface TableApplyRequest<D extends AnyDraft> {
  text: string;
  delimiter: Delimiter;
  has_header: boolean;
  mapping: ColumnMapping[];
  options: TableOptions;
  context: ExtractContext;
  base?: D | null;
}
