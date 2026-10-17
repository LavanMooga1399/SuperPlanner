/**
 * Typed fetch wrappers for every endpoint of docs/ARCHITECTURE.md section 14.
 * All calls go through the relative base `/api/v1` (Vite proxies it to :8000).
 */
import type {
  ApproveRequest,
  ApproveResponse,
  CancelResponse,
  Comparison,
  ErrorEnvelope,
  ExportFile,
  Health,
  InstantiateRequest,
  ListResponse,
  Problem,
  ProblemRecord,
  ProblemSummary,
  ReplanCreated,
  ReplanRequest,
  RunCreated,
  RunEvent,
  Schedule,
  ScheduleStatus,
  ScheduleSummary,
  SolverRun,
  SolverRunRequest,
  TemplateInfo,
  ValidateResponse,
} from "./types";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api/v1";

/** Error raised for every non-2xx response (and network failures, status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function isEnvelope(x: unknown): x is ErrorEnvelope {
  if (typeof x !== "object" || x === null || !("error" in x)) return false;
  const e = (x as { error: unknown }).error;
  return typeof e === "object" && e !== null && "code" in e;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

interface RawResponse<T> {
  data: T;
  headers: Headers;
  status: number;
}

async function raw<T>(path: string, opts: RequestOptions = {}): Promise<RawResponse<T>> {
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(API_BASE + path, { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw networkError();
  }
  if (res.status === 204) {
    return { data: undefined as T, headers: res.headers, status: 204 };
  }
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) {
    if (isEnvelope(parsed)) {
      throw new ApiError(res.status, parsed.error.code, parsed.error.message, parsed.error.details ?? {});
    }
    if (looksLikeProxyFailure(res.status, text)) throw networkError(res.status);
    const detail =
      typeof parsed === "object" && parsed !== null && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : res.statusText || "Request failed";
    throw new ApiError(res.status, `HTTP_${res.status}`, detail);
  }
  return { data: parsed as T, headers: res.headers, status: res.status };
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return (await raw<T>(path, opts)).data;
}

const enc = encodeURIComponent;

/** Parse an ETag value (`"3"`, `W/"3"`, `3`) into a version number. */
export function parseEtag(etag: string | null): number | null {
  if (!etag) return null;
  const m = etag.match(/(\d+)/);
  return m ? Number(m[1]) : null;
}

// ------------------------------------------------------------------ 14.1
export const getHealth = (signal?: AbortSignal) => request<Health>("/health", { signal });

// ------------------------------------------------------------------ 14.2
export const listTemplates = (signal?: AbortSignal) =>
  request<ListResponse<TemplateInfo>>("/templates", { signal });

export const instantiateTemplate = (templateId: string, body: InstantiateRequest) =>
  request<ProblemRecord>(`/templates/${enc(templateId)}/instantiate`, { method: "POST", body });

// ------------------------------------------------------------------ 14.3
export const listProblems = (signal?: AbortSignal) =>
  request<ListResponse<ProblemSummary>>("/problems", { signal });

export const createProblem = (problem: Problem) =>
  request<ProblemRecord>("/problems", { method: "POST", body: problem });

export const getProblem = (id: string, signal?: AbortSignal) =>
  request<ProblemRecord>(`/problems/${enc(id)}`, { signal });

/** Full replacement with optimistic concurrency (`If-Match: "<version>"`). */
export const updateProblem = (id: string, problem: Problem, version: number) =>
  request<ProblemRecord>(`/problems/${enc(id)}`, {
    method: "PUT",
    body: problem,
    headers: { "If-Match": `"${version}"` },
  });

export const deleteProblem = (id: string) => request<void>(`/problems/${enc(id)}`, { method: "DELETE" });

export const exportProblem = (id: string) => request<ExportFile>(`/problems/${enc(id)}/export`);

export const exportUrl = (id: string) => `${API_BASE}/problems/${enc(id)}/export`;

export const importProblem = (file: ExportFile) =>
  request<ProblemRecord>("/problems/import", { method: "POST", body: file });

// ------------------------------------------------------------------ 14.4
export const validateProblem = (id: string) =>
  request<ValidateResponse>(`/problems/${enc(id)}/validate`, { method: "POST" });

// ------------------------------------------------------------------ 14.5
export const createRun = (problemId: string, body: SolverRunRequest) =>
  request<RunCreated>(`/problems/${enc(problemId)}/solver-runs`, { method: "POST", body });

export const listRuns = (problemId: string, signal?: AbortSignal) =>
  request<ListResponse<SolverRun>>(`/problems/${enc(problemId)}/solver-runs`, { signal });

export const getRun = (runId: string, signal?: AbortSignal) =>
  request<SolverRun>(`/solver-runs/${enc(runId)}`, { signal });

export const cancelRun = (runId: string) =>
  request<CancelResponse>(`/solver-runs/${enc(runId)}/cancel`, { method: "POST" });

export const listRunEvents = (runId: string, after = 0) =>
  request<ListResponse<RunEvent>>(`/solver-runs/${enc(runId)}/events?stream=false&after=${after}`);

export const runEventsUrl = (runId: string) => `${API_BASE}/solver-runs/${enc(runId)}/events`;

// ------------------------------------------------------------------ 14.6
export const listSchedules = (problemId: string, status?: ScheduleStatus, signal?: AbortSignal) =>
  request<ListResponse<ScheduleSummary>>(
    `/problems/${enc(problemId)}/schedules${status ? `?status=${status}` : ""}`,
    { signal },
  );

export const getSchedule = (id: string, signal?: AbortSignal) =>
  request<Schedule>(`/schedules/${enc(id)}`, { signal });

export const approveSchedule = (id: string, body: ApproveRequest = {}) =>
  request<ApproveResponse>(`/schedules/${enc(id)}/approve`, { method: "POST", body });

export const compareSchedules = (a: string, b: string, signal?: AbortSignal) =>
  request<Comparison>(`/schedules/compare?a=${enc(a)}&b=${enc(b)}`, { signal });

export const scheduleCsvUrl = (id: string) => `${API_BASE}/schedules/${enc(id)}/export.csv`;

export const replanSchedule = (id: string, body: ReplanRequest) =>
  request<ReplanCreated>(`/schedules/${enc(id)}/replan`, { method: "POST", body });

/** Shown whenever the server cannot be reached (PHASE2.md 3.6). */
export const NETWORK_MESSAGE = "Cannot reach the server. Check that it is running and try again.";

export function networkError(status = 0): ApiError {
  return new ApiError(status, "NETWORK_ERROR", NETWORK_MESSAGE);
}

/**
 * The dev/preview proxy answers 500 with an empty body when the backend is down; gateways answer
 * 502/503/504. Real API errors always carry the A.14 envelope, so these are treated as "unreachable".
 */
export function looksLikeProxyFailure(status: number, text: string): boolean {
  return status === 502 || status === 503 || status === 504 || (status === 500 && text.trim() === "");
}

export function isNetworkError(err: unknown): boolean {
  return err instanceof ApiError && err.code === "NETWORK_ERROR";
}

const LOC_ROOTS = new Set(["body", "query", "path", "header"]);

/** Names of list fields in plan documents (scheduling and finance), singular, for "Task 3". */
const LIST_LABELS: Record<string, string> = {
  tasks: "Task",
  resources: "Resource",
  dependencies: "Dependency",
  requirements: "Requirement",
  alternatives: "Option",
  blocked: "Closed time",
  task_updates: "Change",
  goals: "Goal",
  incomes: "Income",
  expenses: "Expense",
  debts: "Loan",
  holdings: "Savings",
  asset_classes: "Asset class",
  earmarked: "Set-aside amount",
  items: "Item",
};

/** Field labels as the forms show them. Unknown names are turned into words ("start_month" -> "Start month"). */
const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  description: "Description",
  horizon_start: "Plan start",
  horizon_days: "Planning window (days)",
  duration_minutes: "Duration",
  duration_estimate: "Duration range",
  earliest_start: "Earliest start",
  deadline: "Deadline",
  deadline_type: "Deadline type",
  capacity: "Capacity",
  cost_per_hour: "Cost per hour",
  calendar: "Working time",
  weekly: "Weekly working time",
  lag_minutes: "Lag",
  predecessor: "Comes after",
  successor: "Task",
  units: "Units",
  time_limit_seconds: "Time limit",
  weights: "Weights",
  target_amount: "Cost in today's money",
  target_month: "Target month",
  start_month: "Start month",
  end_month: "End month",
  amount: "Amount",
  monthly_amount: "Monthly amount",
  growth_pct: "Yearly raise",
  inflation_pct: "Inflation",
  risk_tolerance: "Risk level",
  min_success_probability: "Minimum chance",
  flexibility_months: "Could wait (months)",
  emergency_months: "Emergency fund (months of expenses)",
  balance: "Balance",
  interest_pct: "Interest rate",
  emi: "Monthly instalment",
  parameters: "Example settings",
  utc_offset: "Time zone",
  start_date: "Start date",
  currency: "Currency",
  locale: "Number format",
};

function words(name: string): string {
  const w = name.replace(/_/g, " ").trim();
  return w ? w[0].toUpperCase() + w.slice(1) : name;
}

/** "["body", "tasks", 2, "duration_minutes"]" -> "Task 3, Duration". Empty for the whole request. */
export function describeLoc(loc: unknown[]): string {
  const parts: string[] = [];
  const path = loc.filter((x, i) => !(i === 0 && typeof x === "string" && LOC_ROOTS.has(x)));
  for (let i = 0; i < path.length; i++) {
    const seg = path[i];
    const next = path[i + 1];
    if (typeof seg === "string" && typeof next === "number" && LIST_LABELS[seg]) {
      parts.push(`${LIST_LABELS[seg]} ${next + 1}`);
      i++;
    } else if (typeof seg === "string") {
      if (seg === "problem" || seg === "plan" || seg === "profile" || seg === "assumptions") continue;
      parts.push(FIELD_LABELS[seg] ?? words(seg));
    }
  }
  return parts.join(", ");
}

function cleanMsg(msg: string): string {
  const m = msg.replace(/^Value error, /, "").replace(/^Assertion failed, /, "");
  return m ? m[0].toUpperCase() + m.slice(1) : m;
}

/** One line per field error of a 422 `VALIDATION_ERROR` (A.14 `details.errors`), with form labels. */
export function fieldErrors(err: unknown): { field: string; message: string; loc: unknown[] }[] {
  if (!(err instanceof ApiError) || err.code !== "VALIDATION_ERROR") return [];
  const list = err.details.errors;
  if (!Array.isArray(list)) return [];
  return list
    .filter((e): e is { loc?: unknown; msg?: unknown } => typeof e === "object" && e !== null)
    .map((e) => {
      const loc = Array.isArray(e.loc) ? e.loc : [];
      return { field: describeLoc(loc), message: cleanMsg(String(e.msg ?? "is not valid")), loc };
    });
}

/** Human-readable message for any thrown value. Validation errors name the fields as the forms label them. */
export function errorMessage(err: unknown): string {
  const fields = fieldErrors(err);
  if (fields.length) {
    const shown = fields.slice(0, 3).map((f) => (f.field ? `${f.field}: ${f.message}` : f.message));
    const more = fields.length > 3 ? ` (and ${fields.length - 3} more)` : "";
    return `Please check ${fields.length === 1 ? "this field" : "these fields"}. ${shown.join("; ")}${more}.`.replace(/\.\.$/, ".");
  }
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** Trigger a browser download of JSON data. */
export function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
