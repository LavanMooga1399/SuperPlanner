/**
 * Typed wrappers for `/api/v1/intake` (PHASE2.md 2.15). Every call is stateless: the whole draft travels
 * with each request and nothing is stored on the server. Reuses the A.14 envelope parsing of `finRequest`.
 */
import { finRequest } from "../../finance/api/client";
import type {
  Answer,
  Capabilities,
  DescribeRequest,
  ExtractContext,
  FinanceBuildResult,
  FinanceDraft,
  FinanceIntakeResponse,
  ScheduleBuildResult,
  ScheduleDraft,
  ScheduleIntakeResponse,
  TableApplyRequest,
  TableParseRequest,
  TableParseResult,
} from "./types";

const I = "/intake";
const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  finRequest<T>(`${I}${path}`, { method: "POST", body, signal });

export const getCapabilities = (signal?: AbortSignal) => finRequest<Capabilities>(`${I}/capabilities`, { signal });

// ---------------------------------------------------------------- schedule
export const describeSchedule = (body: DescribeRequest, signal?: AbortSignal) =>
  post<ScheduleIntakeResponse>("/schedule/describe", body, signal);

export const answerSchedule = (draft: ScheduleDraft, answers: Answer[], context: ExtractContext, signal?: AbortSignal) =>
  post<ScheduleIntakeResponse>("/schedule/answer", { draft, answers, context }, signal);

export const buildSchedule = (draft: ScheduleDraft, context: ExtractContext, signal?: AbortSignal) =>
  post<ScheduleBuildResult>("/schedule/build", { draft, context }, signal);

export const parseScheduleTable = (body: TableParseRequest, signal?: AbortSignal) =>
  post<TableParseResult>("/schedule/table/parse", body, signal);

export const applyScheduleTable = (body: TableApplyRequest<ScheduleDraft>, signal?: AbortSignal) =>
  post<ScheduleIntakeResponse>("/schedule/table/apply", body, signal);

// ---------------------------------------------------------------- finance
export const describeFinance = (body: DescribeRequest, signal?: AbortSignal) =>
  post<FinanceIntakeResponse>("/finance/describe", body, signal);

export const answerFinance = (draft: FinanceDraft, answers: Answer[], context: ExtractContext, signal?: AbortSignal) =>
  post<FinanceIntakeResponse>("/finance/answer", { draft, answers, context }, signal);

export const buildFinance = (draft: FinanceDraft, context: ExtractContext, signal?: AbortSignal) =>
  post<FinanceBuildResult>("/finance/build", { draft, context }, signal);

export const parseFinanceTable = (body: TableParseRequest, signal?: AbortSignal) =>
  post<TableParseResult>("/finance/table/parse", body, signal);

export const applyFinanceTable = (body: TableApplyRequest<FinanceDraft>, signal?: AbortSignal) =>
  post<FinanceIntakeResponse>("/finance/table/apply", body, signal);
